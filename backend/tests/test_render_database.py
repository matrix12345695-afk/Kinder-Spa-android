"""Explicit private Render TLS scope; synthetic connection-status fixtures."""
import unittest
from unittest.mock import MagicMock,patch

from kinder.telegram_runner import connection_factory,database_transport,RENDER_DATABASE_HOST
from kinder.render_api import configuration
from test_render_api import environment


DSN='dbname=kinder_spa_db host='+RENDER_DATABASE_HOST+' sslmode=require'


class RenderDatabaseTests(unittest.TestCase):
    def test_require_is_not_a_generic_external_tls_bypass(self):
        with self.assertRaises(ValueError):connection_factory(DSN,'kinder_spa_db','kinder')
        self.assertFalse(database_transport({}))

    def test_private_scope_requires_exact_database_host_and_encrypted_mode(self):
        for dsn,db in [(DSN.replace(RENDER_DATABASE_HOST,'other.internal'),'kinder_spa_db'),
                       (DSN.replace(RENDER_DATABASE_HOST,RENDER_DATABASE_HOST+'.evil.invalid'),'kinder_spa_db'),
                       (DSN.replace('sslmode=require','sslmode=prefer'),'kinder_spa_db'),
                       (DSN.replace('sslmode=require','sslmode=disable'),'kinder_spa_db'),
                       (DSN.replace('kinder_spa_db','kinder_other'),'kinder_other'),
                       (DSN+' hostaddr=127.0.0.1','kinder_spa_db')]:
            with self.subTest(dsn=dsn),self.assertRaises(ValueError):
                connection_factory(dsn,db,'kinder',render_private=True)

    def test_unknown_transport_refuses_before_any_network_call(self):
        with patch('kinder.telegram_runner.psycopg.connect') as connect:
            with self.assertRaises(ValueError):configuration(environment()|{'KINDER_DATABASE_TRANSPORT':'disable-verification'})
            connect.assert_not_called()

    def test_absent_negotiated_tls_closes_before_schema_queries(self):
        conn=MagicMock();conn.pgconn.ssl_in_use=False
        with patch('kinder.telegram_runner.psycopg.connect',return_value=conn):
            with self.assertRaises(ValueError):connection_factory(DSN,'kinder_spa_db','kinder',render_private=True)()
        conn.close.assert_called_once();conn.execute.assert_not_called()

    def test_tls_is_required_with_minimum_protocol_and_no_gss_fallback(self):
        conn=MagicMock();conn.pgconn.ssl_in_use=True
        conn.execute.return_value.fetchone.return_value=(False,)
        with patch('kinder.telegram_runner.psycopg.connect',return_value=conn) as connect:
            self.assertIs(connection_factory(DSN,'kinder_spa_db','kinder',render_private=True)(),conn)
        connect.assert_called_once_with(DSN,autocommit=True,connect_timeout=3,sslmode='require',ssl_min_protocol_version='TLSv1.2',gssencmode='disable')

    def test_explicit_private_mode_is_only_admitted_after_render_guards(self):
        values=environment()|{'KINDER_DATABASE_URL':DSN,'KINDER_DATABASE_TRANSPORT':'render-private-tls'}
        self.assertTrue(callable(configuration(values).factory))
        self.assertTrue(callable(configuration(values|{'KINDER_DATABASE_URL':DSN.replace(' sslmode=require','')}).factory))
        with self.assertRaises(ValueError):configuration(values|{'RENDER':'false'})
