"""Synthetic Render configuration/startup checks. No provider token or network."""
from contextlib import redirect_stdout
from io import StringIO
import os
import unittest
from unittest.mock import MagicMock, patch

from kinder.telegram_runner import main, render_configuration


TOKEN='123456789:'+('X'*40)


def environment():
    return {
        'RENDER':'true','RENDER_SERVICE_TYPE':'worker',
        'RENDER_SERVICE_NAME':'kinder-spa-telegram','RENDER_SERVICE_ID':'srv-abcdefghijklmnopqrst',
        'KINDER_TELEGRAM_LIVE':'approved','KINDER_TELEGRAM_BOT_ID':'123456789',
        'KINDER_TELEGRAM_BOT_TOKEN':TOKEN,
        'KINDER_DATABASE_URL':'dbname=kinder_spa_db host=fixture.example sslmode=verify-full',
        'KINDER_DATABASE_NAME':'kinder_spa_db','KINDER_DATABASE_SCHEMA':'kinder',
    }


class RenderWorkerTests(unittest.TestCase):
    def test_inspection_mode_routes_only_to_readonly_operator_without_token_access(self):
        values={'KINDER_WORKER_MODE':'inspection'}
        with patch.dict(os.environ,values,clear=True),patch('kinder.render_api.main',return_value=0) as inspect,\
             patch('kinder.telegram_runner.TelegramAPI',side_effect=AssertionError('must not read bot credential')):
            self.assertEqual(main(['--run']),0);inspect.assert_called_once_with(['--inspect-wait'])

    def test_valid_configuration_has_no_network_or_database_side_effect(self):
        with patch('kinder.telegram_runner.psycopg.connect',side_effect=AssertionError('no DB during validation')):
            factory,ident,token=render_configuration(environment())
        self.assertTrue(callable(factory));self.assertEqual(ident,123456789);self.assertEqual(token,TOKEN)

    def test_foreign_service_or_nonrender_markers_do_not_read_token(self):
        class NoToken(dict):
            def __getitem__(self,key):
                if key=='KINDER_TELEGRAM_BOT_TOKEN':raise AssertionError('must not read token')
                return super().__getitem__(key)
        for key,value in [('RENDER','false'),('RENDER_SERVICE_TYPE','web'),
                          ('RENDER_SERVICE_NAME','ultimate-ai-control'),('RENDER_SERVICE_ID',''),
                          ('KINDER_TELEGRAM_LIVE','true')]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                render_configuration(NoToken(environment()|{key:value}))

    def test_foreign_database_rejected_before_token_lookup(self):
        values=environment();values.pop('KINDER_TELEGRAM_BOT_TOKEN')
        values.update(KINDER_DATABASE_NAME='inventory',KINDER_DATABASE_URL='dbname=inventory host=localhost')
        with self.assertRaises(ValueError):render_configuration(values)

    def test_no_file_or_shared_token_fallback(self):
        values=environment();values.pop('KINDER_TELEGRAM_BOT_TOKEN')
        values.update(BOT_TOKEN=TOKEN,TELEGRAM_BOT_TOKEN=TOKEN,KINDER_TELEGRAM_TOKEN_FILE='/etc/secrets/old')
        with self.assertRaises(KeyError):render_configuration(values)

    def test_identity_prefix_and_unstripped_token_must_match(self):
        for change in ({'KINDER_TELEGRAM_BOT_ID':'123456788'},
                       {'KINDER_TELEGRAM_BOT_ID':'00123456789'},
                       {'KINDER_TELEGRAM_BOT_ID':'9223372036854775808'},
                       {'KINDER_TELEGRAM_BOT_TOKEN':TOKEN+'\n'}):
            with self.subTest(change=list(change)),self.assertRaises(ValueError):
                render_configuration(environment()|change)

    def test_startup_failures_do_not_log_credentials_or_dsn(self):
        values=environment();output=StringIO()
        with patch.dict(os.environ,values,clear=True),redirect_stdout(output),\
             patch('kinder.telegram_runner.TelegramAPI',side_effect=RuntimeError(TOKEN+' '+values['KINDER_DATABASE_URL'])):
            self.assertEqual(main(['--once']),2)
        self.assertNotIn(TOKEN,output.getvalue());self.assertNotIn('fixture.example',output.getvalue())

    def test_singleton_refusal_never_configures_or_polls(self):
        with patch.dict(os.environ,environment(),clear=True),\
             patch('kinder.telegram_runner.connection_factory') as factory,\
             patch('kinder.telegram_runner.TelegramAPI'),\
             patch('kinder.telegram_runner.verify_identity',return_value='kinder_fixture_bot'),\
             patch('kinder.telegram_runner.Bot') as bot,\
             patch('kinder.telegram_runner.poll_once') as poll,redirect_stdout(StringIO()):
            factory.return_value.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=(False,)
            self.assertEqual(main(['--once']),2)
            bot.return_value.configure.assert_not_called();poll.assert_not_called()

    def test_one_cycle_start_uses_verified_identity_and_closes_singleton(self):
        connection=MagicMock()
        connection.execute.return_value.fetchone.return_value=(True,)
        with patch.dict(os.environ,environment(),clear=True),\
             patch('kinder.telegram_runner.connection_factory') as factory,\
             patch('kinder.telegram_runner.TelegramAPI') as api,\
             patch('kinder.telegram_runner.verify_identity',return_value='kinder_fixture_bot'),\
             patch('kinder.telegram_runner.Bot') as bot,\
             patch('kinder.telegram_runner.Sender') as sender,\
             patch('kinder.telegram_runner.signal.signal'),\
             patch('kinder.telegram_runner.poll_once') as poll:
            singleton=factory.return_value.return_value
            singleton.__enter__.return_value=connection
            self.assertEqual(main(['--once']),0)
            api.assert_called_once_with(TOKEN)
            bot.return_value.configure.assert_called_once_with(123456789,'kinder_fixture_bot')
            poll.assert_called_once_with(bot.return_value,api.return_value,sender.return_value)
            singleton.__exit__.assert_called_once()
