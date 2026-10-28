"""Render gateway guards, real low-privilege PostgreSQL and Gunicorn HTTP tests."""
from contextlib import contextmanager, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from auth_fixtures import Fixture, PASSWORD
from kinder.gateway import Server, SafeLogger
from kinder.render_api import Configuration, RenderApp, configuration, inspect_database, main, TABLES


ORIGIN = 'https://kinder-fixture.onrender.com'


def environment():
    return {'RENDER':'true', 'RENDER_SERVICE_TYPE':'web', 'RENDER_SERVICE_NAME':'kinder-spa-api',
            'RENDER_SERVICE_ID':'srv-abcdefghijklmnopqrst', 'RENDER_EXTERNAL_URL':ORIGIN,
            'RENDER_EXTERNAL_HOSTNAME':'kinder-fixture.onrender.com', 'KINDER_API_LIVE':'approved',
            'KINDER_DATABASE_URL':'dbname=kinder_spa_db host=fixture.invalid sslmode=verify-full',
            'KINDER_DATABASE_NAME':'kinder_spa_db', 'KINDER_DATABASE_SCHEMA':'kinder'}


class ConfigurationTests(unittest.TestCase):
    def test_disabled_refuses_before_database_credentials(self):
        values=environment();values.pop('KINDER_DATABASE_URL');values['KINDER_API_LIVE']='disabled'
        with self.assertRaises(ValueError): configuration(values)

    def test_nonrender_or_wrong_service_does_not_read_database(self):
        class NoDatabase(dict):
            def __getitem__(self,key):raise AssertionError('must not read a DSN')
        for key,value in [('RENDER','false'),('RENDER_SERVICE_TYPE','worker'),
                          ('RENDER_SERVICE_NAME','inventory-bot'),('RENDER_SERVICE_ID','')]:
            with self.subTest(key=key),self.assertRaises(ValueError): configuration(NoDatabase(environment()|{key:value}))

    def test_canonical_render_origin_not_message_or_forwarded_host(self):
        for url in ('http://kinder-fixture.onrender.com',ORIGIN+'/',ORIGIN+'?secret=x',
                    'https://other.onrender.com','https://user:pass@kinder-fixture.onrender.com'):
            with self.subTest(url=url),self.assertRaises(ValueError): configuration(environment()|{'RENDER_EXTERNAL_URL':url})

    def test_port_range_reserved_and_ambiguous_numbers(self):
        for port in ('0','80','010000','65536','18012','18013','19099','10000,10001'):
            with self.subTest(port=port),self.assertRaises(ValueError): configuration(environment()|{'PORT':port})
        self.assertEqual(configuration(environment()|{'PORT':'12345'}).port,12345)

    def test_telegram_flag_is_explicit_and_default_disabled(self):
        self.assertFalse(configuration(environment()).telegram_links)
        self.assertTrue(configuration(environment()|{'KINDER_API_TELEGRAM_LINKS':'enabled'}).telegram_links)
        with self.assertRaises(ValueError):configuration(environment()|{'KINDER_API_TELEGRAM_LINKS':'false'})

    def test_metadata_inspection_does_not_enable_live_or_connect_during_configuration(self):
        with patch('kinder.telegram_runner.psycopg.connect',side_effect=AssertionError('no connection yet')):
            settings=configuration(environment()|{'KINDER_API_LIVE':'disabled'},inspection=True)
            worker=environment()|{'RENDER_SERVICE_TYPE':'worker','RENDER_SERVICE_NAME':'kinder-spa-telegram',
                                  'RENDER_EXTERNAL_URL':'','RENDER_EXTERNAL_HOSTNAME':''}
            self.assertEqual(configuration(worker,inspection=True).origin,'')
            with self.assertRaises(ValueError):configuration(worker)
            with patch('kinder.render_api.connection_factory') as factory:
                values=environment()|{'KINDER_INSPECTION_DATABASE_URL':'inspection-only-dsn'}
                configuration(values,inspection=True)
                self.assertEqual(factory.call_args.args[0],'inspection-only-dsn')
                configuration(values)
                self.assertEqual(factory.call_args.args[0],values['KINDER_DATABASE_URL'])
        self.assertTrue(callable(settings.factory))

    def test_startup_exception_does_not_disclose_provider_text_or_credentials(self):
        output=StringIO()
        with patch.dict(os.environ,environment(),clear=True),redirect_stdout(output),\
             patch('kinder.render_api.inspect_database',side_effect=RuntimeError('secret-password fixture.invalid')):
            self.assertEqual(main(['--run']),2)
        self.assertNotIn('secret-password',output.getvalue());self.assertNotIn('fixture.invalid',output.getvalue())

    def test_not_ready_refuses_before_starting_listener(self):
        with patch.dict(os.environ,environment(),clear=True),redirect_stdout(StringIO()),\
             patch('kinder.render_api.inspect_database',return_value={'ready':False}),patch('kinder.gateway.Server') as server:
            self.assertEqual(main(['--run']),2);server.assert_not_called()

    def test_inspection_prints_only_metadata_without_starting_listener(self):
        report={'ready':False,'metadata_only':True,'read_only':True};output=StringIO()
        with patch.dict(os.environ,environment()|{'KINDER_API_LIVE':'disabled'},clear=True),redirect_stdout(output),\
             patch('kinder.render_api.inspect_database',return_value=report),patch('kinder.gateway.Server') as server:
            self.assertEqual(main(['--inspect']),1);server.assert_not_called()
        self.assertEqual(json.loads(output.getvalue()),report)

    def test_gateway_environment_cannot_turn_on_logs_or_forwarded_identity(self):
        with patch.dict(os.environ,{'WEB_CONCURRENCY':'99','GUNICORN_CMD_ARGS':'--access-logfile - --workers 99'},clear=True):
            server=Server(lambda e,s:[],12345)
        self.assertEqual(server.cfg.workers,1);self.assertEqual(server.cfg.worker_class_str,'sync')
        self.assertEqual(server.cfg.bind,['0.0.0.0:12345']);self.assertIsNone(server.cfg.accesslog)
        self.assertEqual(server.cfg.forwarded_allow_ips,[]);self.assertEqual(server.cfg.secure_scheme_headers,{})

    def test_logger_discards_raw_message_arguments_and_exception(self):
        logger=SafeLogger.__new__(SafeLogger);logger.error_log=MagicMock()
        for method in ('critical','error','warning','info','debug','exception','log','access'):
            getattr(logger,method)('secret-password URL token=%s','secret-token',exc_info=True)
        value=str(logger.error_log.mock_calls)
        self.assertNotIn('secret-password',value);self.assertNotIn('secret-token',value);self.assertNotIn('exc_info',value)

    def test_inspection_denies_schema_injection_before_connection(self):
        factory=MagicMock()
        with self.assertRaises(ValueError):inspect_database(factory,'public,kinder')
        factory.assert_not_called()

    def test_worker_inspection_standby_never_starts_http_or_polls_when_not_ready(self):
        output=StringIO();values=environment()|{'RENDER_SERVICE_TYPE':'worker','RENDER_SERVICE_NAME':'kinder-spa-telegram',
            'RENDER_EXTERNAL_URL':'','RENDER_EXTERNAL_HOSTNAME':'','KINDER_API_LIVE':'disabled'}
        with patch.dict(os.environ,values,clear=True),redirect_stdout(output),\
             patch('kinder.render_api.inspect_database',return_value={'ready':False,'metadata_only':True}),\
             patch('kinder.render_api.threading.Event') as event,patch('kinder.render_api.signal.signal') as signals,\
             patch('kinder.gateway.Server') as server:
            self.assertEqual(main(['--inspect-wait']),0)
            event.return_value.wait.assert_called_once_with();self.assertEqual(signals.call_count,2)
            server.assert_not_called()
        self.assertIn('telegram_polling=disabled',output.getvalue())


class DatabaseGatewayTests(Fixture):
    def setUp(self):
        super().setUp()
        self.runtime_role='runtime_'+uuid.uuid4().hex
        self.extra_roles=[]
        self.conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT PASSWORD {}').format(sql.Identifier(self.runtime_role),sql.Literal('fixture-only')))
        self.conn.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(self.runtime_role)))
        for name,privileges in TABLES.items():
            self.conn.execute(sql.SQL('GRANT '+privileges+' ON {}.{} TO {}').format(sql.Identifier(self.schema),sql.Identifier(name),sql.Identifier(self.runtime_role)))
        self.conn.execute(sql.SQL('GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(self.runtime_role)))
        parsed=conninfo_to_dict(self.url);parsed.update(user=self.runtime_role,password='fixture-only')
        self.runtime_url=make_conninfo(**parsed)
        self.settings=Configuration(self.runtime_factory,self.schema,ORIGIN,10000,False)
        self.app=RenderApp(self.settings)

    def runtime_factory(self):
        conn=psycopg.connect(self.runtime_url,autocommit=True)
        conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(self.schema)))
        return conn

    def tearDown(self):
        self.conn.rollback()
        for role in self.extra_roles:
            self.conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        self.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.runtime_role)))
        self.conn.close()

    def request(self,method,path,value=None,**kwargs):
        return self.call(method,path,value,environ={'HTTP_HOST':'kinder-fixture.onrender.com','wsgi.url_scheme':'http'}|kwargs)

    def probe(self,**kwargs):return inspect_database(self.runtime_factory,self.schema,**kwargs)

    def test_ready_metadata_does_not_change_accounts_sessions_or_audit(self):
        before=[self.count(t) for t in ('accounts','auth_sessions','audit_events')]
        report=self.probe();self.assertTrue(report['ready']);self.assertTrue(report['read_only'])
        self.assertEqual(before,[self.count(t) for t in ('accounts','auth_sessions','audit_events')])

    def test_absent_table_is_not_ready(self):
        self.conn.execute('ALTER TABLE auth_sessions RENAME TO old_sessions')
        self.assertIn('auth_sessions',self.probe()['missing_tables']);self.assertFalse(self.probe()['ready'])

    def test_view_with_correct_name_does_not_replace_a_real_table(self):
        self.conn.execute('ALTER TABLE auth_sessions RENAME TO old_sessions')
        self.conn.execute('CREATE VIEW auth_sessions AS SELECT * FROM old_sessions')
        self.assertIn('auth_sessions',self.probe()['missing_tables'])

    def test_database_superuser_cannot_be_a_runtime_role(self):
        self.assertFalse(inspect_database(self.factory,self.schema)['runtime_role_safe'])

    def test_table_ownership_is_refused(self):
        self.conn.execute(sql.SQL('ALTER TABLE accounts OWNER TO {}').format(sql.Identifier(self.runtime_role)))
        self.assertFalse(self.probe()['runtime_role_safe'])

    def test_schema_create_permission_is_refused(self):
        self.conn.execute(sql.SQL('GRANT CREATE ON SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(self.runtime_role)))
        self.assertFalse(self.probe()['runtime_role_safe'])

    def test_noninherited_privileged_role_membership_still_refuses(self):
        role='danger_'+uuid.uuid4().hex;self.extra_roles.append(role)
        self.conn.execute(sql.SQL('CREATE ROLE {} CREATEDB').format(sql.Identifier(role)))
        self.conn.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(role),sql.Identifier(self.runtime_role)))
        self.assertFalse(self.probe()['runtime_role_safe'])

    def test_missing_mutation_permission_is_not_ready(self):
        self.conn.execute(sql.SQL('REVOKE UPDATE ON allowances FROM {}').format(sql.Identifier(self.runtime_role)))
        report=self.probe();self.assertFalse(report['ready']);self.assertIn('allowances:UPDATE',report['insufficient_privileges'])

    def test_audit_mutation_privileges_are_refused(self):
        self.conn.execute(sql.SQL('GRANT DELETE ON audit_events TO {}').format(sql.Identifier(self.runtime_role)))
        self.assertIn('audit_events:mutable',self.probe()['insufficient_privileges']);self.assertFalse(self.probe()['ready'])

    def test_link_feature_requires_full_telegram_migration_and_scoped_grants(self):
        self.assertFalse(self.probe(telegram_links=True)['ready'])
        self.conn.execute((Path(__file__).parents[1]/'telegram_schema.sql').read_text())
        self.conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}').format(sql.Identifier(self.schema),sql.Identifier(self.runtime_role)))
        self.conn.execute(sql.SQL('GRANT INSERT,UPDATE ON telegram_link_codes TO {}').format(sql.Identifier(self.runtime_role)))
        self.assertTrue(self.probe(telegram_links=True)['ready'])

    def test_every_metadata_select_runs_inside_read_only_transaction(self):
        outer=self;seen=[]
        class Guard:
            def __init__(self):self.conn=outer.runtime_factory()
            @property
            def pgconn(self):return self.conn.pgconn
            def __enter__(self):self.conn.__enter__();return self
            def __exit__(self,*a):return self.conn.__exit__(*a)
            def transaction(self):return self.conn.transaction()
            def execute(self,query,args=None):
                if query.lstrip().startswith('SELECT'):
                    outer.assertEqual(self.conn.execute('SHOW transaction_read_only').fetchone()[0],'on');seen.append(True)
                else:outer.assertTrue(query.startswith('SET '))
                return self.conn.execute(query,args)
        self.assertTrue(inspect_database(Guard,self.schema)['ready']);self.assertGreater(len(seen),10)

    def test_health_exposes_no_schema_or_privilege_metadata(self):
        status,value,headers=self.request('GET','/health')
        self.assertEqual((status,value),(200,{'ok':True}));self.assertIn('Strict-Transport-Security',headers)
        self.conn.execute(sql.SQL('REVOKE INSERT ON bookings FROM {}').format(sql.Identifier(self.runtime_role)))
        self.assertEqual(self.request('GET','/health')[:2],(503,{'error':'not_ready'}))

    def test_forwarded_host_origin_and_client_ip_cannot_change_scope(self):
        self.assertEqual(self.request('GET','/health',HTTP_HOST='evil.invalid',HTTP_X_FORWARDED_HOST='kinder-fixture.onrender.com')[0],421)
        self.assertEqual(self.request('GET','/health',HTTP_ORIGIN='https://evil.invalid',HTTP_X_FORWARDED_PROTO='https')[0],403)
        for n in range(6):
            status,_,_=self.request('POST','/v1/login',{'login':'unknown_fixture','password':PASSWORD},
                                  HTTP_X_FORWARDED_FOR='198.51.100.'+str(n+1),HTTP_FORWARDED='for=198.51.100.'+str(n+1))
        self.assertEqual(status,429)

    @contextmanager
    def wire_gateway(self):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        code='''import os
from psycopg import connect,sql
from kinder.render_api import Configuration,RenderApp
from kinder.gateway import Server
def factory():
 c=connect(os.environ['FIXTURE_DSN'],autocommit=True)
 c.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(os.environ['FIXTURE_SCHEMA'])))
 return c
Server(RenderApp(Configuration(factory,os.environ['FIXTURE_SCHEMA'],'https://kinder-fixture.onrender.com',int(os.environ['FIXTURE_PORT']),False)),int(os.environ['FIXTURE_PORT'])).run()
'''
        env=os.environ.copy();env.update(FIXTURE_DSN=self.runtime_url,FIXTURE_SCHEMA=self.schema,FIXTURE_PORT=str(port),PYTHONPATH=str(Path(__file__).parents[1]))
        with tempfile.TemporaryFile() as logs:
            process=subprocess.Popen([sys.executable,'-c',code],env=env,stdout=logs,stderr=logs,start_new_session=True)
            try:
                for _ in range(100):
                    if process.poll() is not None:raise AssertionError('synthetic gateway exited')
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1):break
                    except OSError:time.sleep(.05)
                else:raise AssertionError('synthetic gateway not listening')
                yield port,logs
            finally:
                if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)

    def test_real_gunicorn_http_login_me_and_header_limits_without_secret_logs(self):
        with self.wire_gateway() as (port,logs):
            base='http://127.0.0.1:'+str(port)
            request=urllib.request.Request(base+'/v1/login',data=json.dumps({'login':'client_fixture','password':PASSWORD}).encode(),
                headers={'Host':'kinder-fixture.onrender.com','Content-Type':'application/json','X-Forwarded-Proto':'http'})
            with urllib.request.urlopen(request,timeout=5) as response:token=json.load(response)['access_token']
            with urllib.request.urlopen(urllib.request.Request(base+'/v1/me',headers={'Host':'kinder-fixture.onrender.com','Authorization':'Bearer '+token}),timeout=5) as response:
                self.assertEqual(json.load(response),{'account_id':self.client,'role':'client'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(urllib.request.Request(base+'/health',headers={'Host':'kinder-fixture.onrender.com','X-Oversize':PASSWORD+'x'*5000}),timeout=5)
            self.assertIn(caught.exception.code,(400,431));caught.exception.close()
            logs.seek(0);raw=logs.read().decode()
            for value in (PASSWORD,token,'fixture-only',self.runtime_url,'X-Oversize'):
                self.assertNotIn(value,raw)
